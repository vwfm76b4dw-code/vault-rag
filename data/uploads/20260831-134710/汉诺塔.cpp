#include <bits/stdc++.h>
using namespace std;
int cnt;
void move(int n,char a,char b,char c){
	if(n==1){
		cout<<a<<"->"<<c<<endl;
		cnt++;
	}else{
		move(n-1,a,c,b);
		cout<<a<<"->"<<c<<endl;
		move(n-1,b,a,c);
	}
}
int main()
{
	cout<<"请输入盘子的数量：";
	int n;
	cin>>n;
	move(n+1,'A','B','C');
	cout<<"一共用了"<<cnt-1<<"次";
}
