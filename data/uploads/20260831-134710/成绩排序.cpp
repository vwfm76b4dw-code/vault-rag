#include <bits/stdc++.h>
using namespace std;
struct student{
	string name;
	int num;
}a[100000];
int main()
{
	int n;
	cin>>n;
	for(int i=1;i<=n;i++){
		cin>>a[i].name>>a[i].num;
	}
	for(int i=0;i<n;i++){
		for(int j=1;j<n-i;j++){
			if(a[j].num<a[j+1].num)swap(a[j],a[j+1]);
			if(a[j].num==a[j+1].num){
				if(a[j+1].name<a[j].name)swap(a[j],a[j+1]);
			}
		}
	}
	for(int i=1;i<=n;i++){
		cout<<a[i].name<<ends<<a[i].num<<endl;
	}
	return 0;
}

