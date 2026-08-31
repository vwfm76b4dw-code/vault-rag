#include <bits/stdc++.h>
using namespace std;
struct student{
	string name;
	int num;
}a[100000];
bool cmp(student a,student b){
	if(a.num!=b.num) return a.num>b.num;
	else if(a.num<b.num) return a.num>b.num;
}
int main()
{
	int n;
	cin>>n;
	for(int i=1;i<=n;i++){
		cin>>a[i].name>>a[i].num;
	}
    sort(a+1,a+n+1,cmp);
	for(int i=n;i>=1;i--){
		cout<<a[i].name<<ends<<a[i].num<<endl;
	}
	return 0;
}

