#include<bits/stdc++.h>
using namespace std;
char str[25*2500+10];
int cnt;
void pingpong(int n){
	int a=0,b=0;
	for(int i=0;i<cnt;i++){
		if(str[i]=='W')a++;
		if(str[i]=='L')b++;
		if((a>=n||b>=n)&&abs(a-b)>=2){
			cout<<a<<":"<<b<<endl;
			a=0,b=0;
		}
	}
	if(a!=0||b!=0)
	cout<<a<<":"<<b;
}
int main()
{
	char ch;
	while(cin>>ch&&ch!='E'){
		if(ch=='L'||ch=='W')str[cnt++]=ch;
	}
	pingpong(11);
	cout<<endl;
	pingpong(21);
}
